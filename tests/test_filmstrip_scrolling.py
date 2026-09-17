from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from fotozeef.core.library import Library
from fotozeef.core.models import ProjectSettings
from fotozeef.core.thumbnails import ThumbnailCache
from fotozeef.ui.main_window import MainWindow

PHOTOS = 120


@pytest.fixture
def window(app: QApplication, tmp_path: Path, library: Library, jpeg_factory) -> MainWindow:
    source = tmp_path / "cam"
    for index in range(PHOTOS):
        jpeg_factory(
            source / f"IMG_{index:04d}.JPG",
            captured_at=datetime(2024, 1, 1, 9, index // 60, index % 60),
        )
    project = library.create_project("shoot", [source], tmp_path / "out", ProjectSettings())
    window = MainWindow(library, ThumbnailCache(tmp_path / "cache"))
    window.resize(1280, 860)
    window.show()
    window._on_project_opened(library.open_project(project.id))
    app.processEvents()
    yield window
    window.close()


def _press(window: MainWindow, key: Qt.Key) -> None:
    window.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _offscreen(window: MainWindow) -> tuple[int, int] | None:
    strip = window._filmstrip
    index = strip.currentIndex()
    rect = strip.visualRect(index)
    viewport = strip.viewport().width()
    if not rect.isValid() or rect.left() < 0 or rect.right() > viewport:
        return (index.row(), rect.x())
    return None


def test_cursor_stays_visible_stepping_forward(window: MainWindow, app: QApplication) -> None:
    lost: list[tuple[int, int]] = []
    for _ in range(PHOTOS - 1):
        _press(window, Qt.Key.Key_Right)
        app.processEvents()
        off = _offscreen(window)
        if off is not None:
            lost.append(off)

    assert lost == [], f"cursor scrolled out of view at (row, x): {lost}"


def test_cursor_stays_visible_stepping_back_from_the_end(
    window: MainWindow, app: QApplication
) -> None:
    _press(window, Qt.Key.Key_End)
    app.processEvents()
    lost: list[tuple[int, int]] = []
    for _ in range(PHOTOS - 1):
        _press(window, Qt.Key.Key_Left)
        app.processEvents()
        off = _offscreen(window)
        if off is not None:
            lost.append(off)

    assert lost == [], f"cursor scrolled out of view at (row, x): {lost}"


def test_cursor_stays_visible_across_page_jumps(window: MainWindow, app: QApplication) -> None:
    lost: list[tuple[int, int]] = []
    for key in (
        Qt.Key.Key_PageDown,
        Qt.Key.Key_PageDown,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_End,
        Qt.Key.Key_Home,
        Qt.Key.Key_PageDown,
    ):
        _press(window, key)
        app.processEvents()
        off = _offscreen(window)
        if off is not None:
            lost.append(off)

    assert lost == [], f"cursor scrolled out of view at (row, x): {lost}"


def test_the_whole_item_fits_inside_the_strip(window: MainWindow) -> None:
    strip = window._filmstrip
    rect = strip.visualRect(strip.model().index(0, 0))

    assert rect.height() <= strip.viewport().height()
    assert rect.bottom() <= strip.viewport().height()
