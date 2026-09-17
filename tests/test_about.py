from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QTabWidget, QTextBrowser

from fotozeef.appinfo import APP_VERSION, THIRD_PARTY_PATH
from fotozeef.core.library import Library
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.about_dialog import AboutDialog
from fotozeef.ui.main_window import MainWindow

REPO = Path(__file__).resolve().parents[1]


def test_the_repository_carries_a_license() -> None:
    license_file = REPO / "LICENSE"

    assert license_file.is_file(), "pyproject declares MIT but there is no LICENSE file"
    assert "MIT License" in license_file.read_text(encoding="utf-8")


def test_the_third_party_notice_ships_with_the_package() -> None:
    assert THIRD_PARTY_PATH.is_file()
    text = THIRD_PARTY_PATH.read_text(encoding="utf-8")

    for component in ("Qt 6", "libheif", "libx265", "LibRaw", "Pillow", "rawpy"):
        assert component in text, f"{component} is not listed in the third-party notice"


def test_the_notice_flags_the_copyleft_component() -> None:
    text = THIRD_PARTY_PATH.read_text(encoding="utf-8")

    assert "GPL-2.0" in text
    assert "distribut" in text.lower()


def test_the_about_dialog_opens_with_three_tabs(app: QApplication) -> None:
    dialog = AboutDialog()
    tabs = dialog.findChild(QTabWidget)

    assert tabs is not None
    assert tabs.count() == 3
    dialog.close()


def test_the_about_dialog_shows_the_version(app: QApplication) -> None:
    dialog = AboutDialog()
    text = " ".join(browser.toPlainText() for browser in dialog.findChildren(QTextBrowser))

    assert APP_VERSION in text
    assert "MIT" in text
    dialog.close()


def test_the_licenses_tab_renders_the_notice(app: QApplication) -> None:
    dialog = AboutDialog()
    text = " ".join(browser.toPlainText() for browser in dialog.findChildren(QTextBrowser))

    assert "libx265" in text
    assert "LibRaw" in text
    dialog.close()


def test_the_help_menu_offers_about(app: QApplication, tmp_path: Path, library: Library) -> None:
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    titles = [
        menu.title() for menu in window.menuBar().findChildren(type(window.menuBar().addMenu("x")))
    ]

    assert any("Help" in title for title in titles)
    assert hasattr(window, "show_about")
    window.close()


def test_the_about_box_names_its_author_and_drops_the_bundle_id(app: QApplication) -> None:
    dialog = AboutDialog()
    text = " ".join(browser.toPlainText() for browser in dialog.findChildren(QTextBrowser))

    assert "Johan Montenij" in text
    assert "nl.j87.FotoZeef" not in text, "the bundle identifier is developer trivia"
    assert "telemetry" not in text.lower()
    dialog.close()


def _assert_ours(directory: Path) -> None:
    """The base belongs to the platform; everything from FotoZeef down is ours."""
    from fotozeef.appinfo import APP_AUTHOR, APP_NAME

    parts = directory.parts
    assert APP_AUTHOR not in str(directory), f"the author's name leaked into {directory}"
    assert APP_NAME in parts, f"{directory} does not sit under {APP_NAME}"
    ours = parts[parts.index(APP_NAME) :]
    assert all(" " not in part for part in ours), f"a space in a folder we chose: {ours}"


def test_the_author_stays_out_of_filesystem_paths() -> None:
    from fotozeef.appinfo import cache_dir, data_dir

    _assert_ours(data_dir())
    _assert_ours(cache_dir())


def test_the_layout_holds_on_the_platforms_this_machine_can_compute() -> None:
    """Windows resolves its folders through the Win32 API, so CI covers that one."""
    from platformdirs.macos import MacOS
    from platformdirs.unix import Unix

    from fotozeef.appinfo import APP_NAME

    for platform in (Unix, MacOS):
        dirs = platform(appname=APP_NAME, appauthor=False)
        _assert_ours(Path(dirs.user_data_dir))
        _assert_ours(Path(dirs.user_cache_dir))
