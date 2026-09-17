from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QApplication

from fotozeef.appinfo import I18N_DIR
from fotozeef.ui.translations import install, preferred_language

CATALOGUES = sorted(I18N_DIR.glob("*.ts"))


def test_there_is_at_least_one_catalogue() -> None:
    assert CATALOGUES, "no .ts files found"


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda path: path.stem)
def test_every_string_is_translated(catalogue: Path) -> None:
    root = ET.parse(catalogue).getroot()
    untranslated: list[str] = []
    for context in root.findall("context"):
        for message in context.findall("message"):
            translation = message.find("translation")
            empty = translation is None or not (translation.text or "").strip()
            unfinished = translation is not None and translation.get("type") in {
                "unfinished",
                "obsolete",
            }
            if empty or unfinished:
                untranslated.append(f"{context.findtext('name')}: {message.findtext('source')}")

    assert untranslated == [], f"{catalogue.name} has untranslated strings: {untranslated}"


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda path: path.stem)
def test_the_compiled_catalogue_matches_its_source(catalogue: Path, app: QApplication) -> None:
    """Compares content, not timestamps: git checkouts do not preserve mtimes."""
    compiled = catalogue.with_suffix(".qm")
    assert compiled.is_file(), f"{compiled.name} is missing; run pyside6-lrelease"

    translator = QTranslator()
    assert translator.load(str(compiled)), f"{compiled.name} could not be loaded"

    stale: list[str] = []
    for context in ET.parse(catalogue).getroot().findall("context"):
        name = context.findtext("name") or ""
        for message in context.findall("message"):
            source = message.findtext("source") or ""
            expected = message.findtext("translation") or ""
            actual = translator.translate(name, source)
            if actual != expected:
                stale.append(f"{name}: {source!r} gives {actual!r}, expected {expected!r}")

    assert stale == [], f"{compiled.name} is out of date; run pyside6-lrelease: {stale}"


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda path: path.stem)
def test_placeholders_survive_translation(catalogue: Path) -> None:
    root = ET.parse(catalogue).getroot()
    broken: list[str] = []
    for context in root.findall("context"):
        for message in context.findall("message"):
            source = message.findtext("source") or ""
            translated = message.findtext("translation") or ""
            expected = [part for part in ("{0}", "{1}", "{2}", "{3}", "{4}") if part in source]
            if any(part not in translated for part in expected):
                broken.append(f"{context.findtext('name')}: {source!r} -> {translated!r}")

    assert broken == [], f"placeholders lost in {catalogue.name}: {broken}"


def test_dutch_catalogue_loads_and_translates(app: QApplication, monkeypatch) -> None:
    monkeypatch.setenv("FOTOZEEF_LANG", "nl")
    translator = QTranslator()
    assert translator.load(str(I18N_DIR / "fotozeef_nl.qm"))
    app.installTranslator(translator)
    try:
        assert QCoreApplication.translate("MainWindow", "No project open") == "Geen project geopend"
        assert QCoreApplication.translate("StartScreen", "Recent projects") == "Recente projecten"
    finally:
        app.removeTranslator(translator)


def test_language_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("FOTOZEEF_LANG", "nl_NL")
    assert preferred_language() == "nl"

    monkeypatch.setenv("FOTOZEEF_LANG", "en")
    assert preferred_language() == "en"


def test_an_unknown_language_falls_back_to_english(app: QApplication, monkeypatch) -> None:
    monkeypatch.setenv("FOTOZEEF_LANG", "xx")

    assert install(app) == "en"
